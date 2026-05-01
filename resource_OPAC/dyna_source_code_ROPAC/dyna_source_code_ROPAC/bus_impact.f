      subroutine bus_impact(i,j,xpos,imbus)     
c -- 
c -- This subroutine calculates the effect of the bus on the current link.
c  -- busimpact is used to simulate the impact caused by
c  -- bus stop.  Currently, 4 different situations are identified
c  -- 0 : nostop
c  -- 1 : stop at the end of the link.
c  -- 2 : stop at the midblock (middle of the link)
c  -- 3 : stop at the midblock curb lane (middle of the link with stop bay)
c --
c -- This subroutine is called from vehicle_moving and does not call any other
c -- subroutines.
c -- INPUT : 
c --       i : current link.
c --       j : vehicle ID for the bus.
c --    xpos : position of the bus on link i at the end of the current 
c --           simulation interval.
c --
c -- OUTPUT : 
c --   imbus : 0 if the bus is not stopping on link i during the current
c --           simulation interval and 1 otherwise.
c --   xl(i) : adjusted link lane.mile length
c --  capacity(i,j) : adjusted link capacity for all movements (j)
c --                  (for bus stop case 1 only)
c --
      use muc_mod
      use vector_mod
      integer::icasetmp = 0
      integer::istoptmp = 0
c --
c --  idbus : the bus number which correspond to the vehicle ID
c --  nubus : number of simulated buses 
c --
      idbus=0
      do ih=1,nubus
        if(busid(ih).eq.j) idbus=ih
      enddo

      if(idbus.eq.0) go to 100
c --
c -- icase : type of stop on the current link (see the definition in
c --         the begining of this file).
c -- 
c -- istop : is a temparary variable to keep the link number in the 
c --         bus path sequence.
c --
      istop=icurrnt(j)+1

c      icase=busstop(idbus,istop)

      icase=BusAtt_Value(idbus,istop,2)
c -- 
c -- icase = 0 , no stop go to the end of the subroutine
c --
      if(icase.eq.0) goto 100
c --
c -- the number 0.0075 is location of the bus stop at the end of the link.
c -- the bus stop is 40 ft from the end of the link so, 0.0075=40/5280
c --
c -- if icase =1, then there is a stop at the end of the link i.
c --  
c --
c -- the negative value (-1) for busstop(idbus,istop) indicates 
c -- a stop at the end of the current link. 
c --
c -- tt : is the time between the end of the simulation interval
c --      and the instance at which the bus reaches the stop.
c --
c -- The negative value for bustime indicates the remaining time for the
c -- bus to stop on the current link.  When the bus raeches a stop, it 
c -- is required
c -- to stop for the dwelling time.  When bustime is not negative, this
c -- means that the bus will start moving again.
c --
      if(icase.eq.1.and.xpos.lt.0.0075) then
         icasetmp=-1*icase
         call BusAtt_Insert(idbus,istop,2,icasetmp)
         bustime(idbus)=-(busdwell(idbus))
	   tt=(0.0075-xpos)/v(i)
         distans(j)=distans(j)+xpar(j)-0.0075
         ttstop(j)=ttstop(j)+tt
         ttilnow(j)=ttilnow(j)+tt
c --     add to GUITotalTime
         GuiTotalTime=GuiTotalTime+tt
         bustime(idbus)=bustime(idbus)+tt
         xpos=0.0075
         xpar(j)=0.0075
c --
c -- Set imbus to 1 to indicate that this bus is stopping.
c -- 
         imbus=1
      endif
c --
c -- If busstop equal (-1) this means that the bus is stopping at the 
c -- end of the current link. So, reduce the available capacity on the   
c -- current link and accumulate the bus stoptime. 
c --    
      if(busstop(idbus,istop).eq.-1) then
         bustime(idbus)=bustime(idbus)+tii
        if(bustime(idbus).le.0) then
c --
c -- reduce the output flow rate, assuming that the bus will block
c -- one lane.  For the total lane.mile length of the link (xl), the
c -- bus is assumed to block the lane for half of the link length.
c --
             imbus=1
             xpos=0.0075
             xpar(j)=0.0075
             ttstop(j)=ttstop(j)+tii
             ttilnow(j)=ttilnow(j)+tii
c --         add to GUITotalTime
             GuiTotalTime=GuiTotalTime+tii
c --  need to consider if the reduction in xl will cause inconsisency between maxden*xl and partotal
             xltemp = s(i)*(nlanes(i)-0.5)
             xl(i)=max(xltemp,partotal(i)/maxden)
           do k=1,llink(i,nu_mv+1)
             capacity(i,k)=capacity(i,k)-(capacity(i,k)/nlanes(i))
           end do
c  --
c -- If bustime > 0, this means that the bus will start moving.
c -- imbus is set to 1, for this time interval because all the 
c -- calculations for the bus are performed in this file.  When imbus is 
c -- zero, the calculations will be performed in linkmove.
c --
        else
           imbus=1
           xpos=xpar(j)-v(i)*tii
           if(xpos.lt.0) xpos=0
           tocross(j)=xpar(j)/v(i)
           tleft(j)=tii-tocross(j)
           xlold=s(i)*nlanes(i)
           ttstop(j)=ttstop(j)+(tii-bustime(idbus))
           ttilnow(j)=ttilnow(j)+(tii-bustime(idbus))
c --       add to GUITotalTime
           GuiTotalTime=GuiTotalTime+(tii-bustime(idbus))

           call BusAtt_Insert(idbus,istop,2,99)
c --
c -- when bus stop is 99, it means that the bus has already stopped and
c -- started moving on the current link.
c --
c  --
c  -- get an average on xl for this time interval
c  -- 
           xltemp=nlanes(i)*s(i)-(s(i)/2)*(tii-bustime(idbus))/tii
	     xl(i)=max(xltemp,partotal(i)/maxden)
        endif
      endif
c --
c -- If icase equal 2, the bus will stop at the middle of the link.
c --
c -- This case follows the same logic as case 1, except for the position
c -- of the stop and the capacity is not affected by the bus stop.
c -- 
      if(icase.eq.2.and.(xpos.lt.s(i)/2) )then
c  -- 
c      if(busstop(idbus,istop).gt.0) then
c         busstop(idbus,istop)=(-1)*busstop(idbus,istop)
         istoptmp = (-1)*busstop(idbus,istop)
         call BusAtt_Insert(idbus,istop,2,istoptmp)
         bustime(idbus)=-(busdwell(idbus))
         tt=(s(i)/2-xpos)/v(i)
         distans(j)=distans(j)+xpar(j)-s(i)/2
         ttstop(j)=ttstop(j)+tt
         ttilnow(j)=ttilnow(j)+tt
c --     add to GUITotalTime
         GuiTotalTime=GuiTotalTime+tt
         bustime(idbus)=bustime(idbus)+tt
         xpos=s(i)/2
         xpar(j)=s(i)/2
         imbus=1
      endif
      if(busstop(idbus,istop).eq.-2) then
         bustime(idbus)=bustime(idbus)+tii
        if(bustime(idbus).le.0) then
           imbus=1
           xltemp=s(i)*(nlanes(i)-0.5)
	     xl(i)=max(xltemp,partotal(i)/maxden)
           ttstop(j)=ttstop(j)+tii
           ttilnow(j)=ttilnow(j)+tii
c --       add to GUITotalTime
           GuiTotalTime=GuiTotalTime+tii
           xpos=s(i)/2
           xpar(j)=s(i)/2
        else
            imbus=1
           xpos=xpar(j)-v(i)*tii
           if(xpos.lt.0) xpos=0
           tocross(j)=xpar(j)/v(i)
           tleft(j)=tii-tocross(j)
           xlold=s(i)*nlanes(i)
           ttstop(j)=tii-bustime(idbus)+ttstop(j)
           ttilnow(j)=ttilnow(j)+tii-bustime(idbus)
c --       add to GUITotalTime
           GuiTotalTime=GuiTotalTime+tii-bustime(idbus)

           call BusAtt_Insert(idbus,istop,2,99)
c  --
c  -- get an average on xl for this time interval
c  -- [s*(nlanes-1/2)*(tii-bustime)+s/2*nlanes*bustime]/tii
c  --
           xltemp=nlanes(i)*s(i)-(s(i)/2)*(tii-bustime(idbus))/tii
		 xl(i)=max(xltemp,partotal(i)/maxden)
        endif
       endif
c --
c -- If icase equal 3, the bus will stop at the middle of the link in 
c -- a stop bay.
c --
c -- This case follows the same logic as case 1, except for the position
c -- of the stop and the capacity is not affected by the bus stop.
c -- 
      if(icase.eq.3.and.(xpos.lt.s(i)/2)) then
c  -- 
c  -- shorterm blockage : the blockage time :4 seconds which is the time
c --  required for the bus to move from the main lanes to the stop bay. 
c  --
c         busstop(idbus,istop)=(-1)*busstop(idbus,istop)
         istoptmp = (-1)*busstop(idbus,istop)
         call BusAtt_Insert(idbus,istop,2,istoptmp)
         bustime(idbus)=-(busdwell(idbus))
         tt=(s(i)/2-xpos)/v(i)
         distans(j)=distans(j)+xpar(j)-s(i)/2
         ttstop(j)=ttstop(j)+tt
         ttilnow(j)=ttilnow(j)+tt
c --     add to GUITotalTime
         GuiTotalTime=GuiTotalTime+tt

         bustime(idbus)=bustime(idbus)+tt
c -- 
c -- 0.067 = 4sec/60
c --
         xltemp=nlanes(i)*s(i)-((s(i)/2)*0.067/tii)
	   xl(i)=max(xltemp,partotal(i)/maxden)
         xpos=s(i)/2
         xpar(j)=s(i)/2
         imbus=1
      endif

      if(busstop(idbus,istop).eq.-3) then
         bustime(idbus)=bustime(idbus)+tii
       if(bustime(idbus).lt.0) then
         imbus=1
         ttstop(j)=ttstop(j)+tii
         ttilnow(j)=ttilnow(j)+tii
c --     add to GUITotalTime
         GuiTotalTime=GuiTotalTime+tii

         xl(i)=nlanes(i)*s(i)
         xpos=s(i)/2
         xpar(j)=s(i)/2
       elseif(bustime(idbus).ge.0) then
         imbus=1
           xpos=xpar(j)-v(i)*tii
           if(xpos.lt.0) xpos=0
           tocross(j)=xpar(j)/v(i)
           tleft(j)=tii-tocross(j)
           xlold=s(i)*nlanes(i)
           ttstop(j)=ttstop(j)+(tii-bustime(idbus))
           ttilnow(j)=ttilnow(j)+tii-bustime(idbus)
c --       add to GUITotalTime
           GuiTotalTime=GuiTotalTime+tii-bustime(idbus)

           call BusAtt_Insert(idbus,istop,2,99)
       endif
      endif
c --
100   continue
      return
      end
