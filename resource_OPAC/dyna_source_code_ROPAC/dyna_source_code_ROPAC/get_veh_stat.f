         subroutine get_veh_stat(i,j,t)
! -- 
! -- This subroutine collects statistics for the vehicle when it 
! -- reaches the destination.  It also print out the vehicle trajectory
! -- information for GUI
! -- 
! -- This subroutine is called from vehicle_moving 
! -- This subroutine does not call any subroutines.
! --
! -- INPUT :
! --     i : current link
! --     j : current vehicle
! --     t : current clock time
! --
! -- OUTPUT :
! --   cumulative statistics for all vehicles which reached their destination
! --   fort.18 : vehicle trajectory (if selected by the user)
! --   fort.188 : vehicle trajectory for buses (if selected by the user)
! --
! -- GUI
! --   for GUI purpose, the following tag numbering scheme applies
! --       TAGGED    NON-TAGGED
! --   in     1          0
! --  out     2          3
! --  in this subroutine, only 2, 3 will apply
	use muc_mod
	use vector_mod
	integer Index1D
	real value
	real www

	if(vehclass2(j).ne.7) ktotal_out=ktotal_out+1
   	atime(j) = t + tocross(j)

   	if(atime(j).lt.stime(j)) then
     	write(911,*) 'ERROR on arrival time for vehicle ',j
     	write(911,*) 'arrival time= ',atime(j),' start time= ',stime(j)
     	stop
   	endif

   	notin(j)=1
   	if(itag(j).eq.0) then
     	nout_nontag=nout_nontag+1
   	elseif(itag(j).eq.1) then
     	numcars=numcars - 1
     	nout_tag=nout_tag+1
     	itag(j)=2
   	endif

c   call VhcAtt_Insert(j,icurrnt(j),3,ttilnow(j)) !3 is for pathtime


   	call VhcAtt_Insert(j,icurrnt(j),3,t-stime(j)) !3 is for pathtime
   	call VhcAtt_Insert(j,icurrnt(j),2,ttstop(j)) !2 is for stoptime
   	if(icurrnt(j).eq.1) then
     	call VhcAtt_Insert(j,icurrnt(j),4,ttilnow(j)) !3 is for pathtime
   	else
     	Index1D = icurrnt(j)-1
!     value = ttilnow(j)-VhcAtt_value(j,Index1D,3)
      	value = t-stime(j)-VhcAtt_value(j,Index1D,3)

     	call VhcAtt_Insert(j,icurrnt(j),4,value) !3 is for pathtime
   	endif
! --
! -- Output the path information for the vehicle.
! --
      if(i18.gt.0)then
!     tmp1=atime(j)-stime(j)

     	tmp1=ttilnow(j)

   	if(itag(j).eq.0) then !for GUI purpose, if the itag = 0 write out as 3
       write(18,1890) j,3,jorigin(j),jdest(j),vehclass(j),
     +  nodenum(iunod(isec(j))),nodenum(nint(VhcAtt_Value(j,1,1))),
     +  nodenum(nint(VhcAtt_Value(j,VhcAtt_Size(j)-1,1))),stime(j),
     +  tmp1,nnpath(j)-1,vehclass2(j),ioc(j)
	 else
       write(18,1890) j,itag(j),jorigin(j),jdest(j),vehclass(j),
     +  nodenum(iunod(isec(j))),nodenum(nint(VhcAtt_Value(j,1,1))),
     +  nodenum(nint(VhcAtt_Value(j,VhcAtt_Size(j)-1,1))),stime(j),
     +  tmp1,nnpath(j)-1,vehclass2(j),ioc(j)
	 endif
      write(18,1891) (nodenum(nint(VhcAtt_Value(j,js,1))),
     + js=1,VhcAtt_Size(j)-1)
      write(18,*)    '==>Node Exit Time Point'
      write(18,1892) (VhcAtt_Value(j,jn,3),jn=1,VhcAtt_Size(j)-1) ! pathtime
      write(18,*)    '==>Link Travel Time'
      write(18,1892) (VhcAtt_Value(j,jn,4),jn=1,VhcAtt_Size(j)-1) ! timediff
      write(18,*)    '==>Accumulated Stop Time'
      write(18,1892) (VhcAtt_Value(j,jn,2),jn=1,VhcAtt_Size(j)-1) ! pathstop
      write(18,*)

1890  format('Veh #',i7,'Tag=',i2,'OrigZ=',i3,'DestZ=',i3,'Class=',i2,
     + 'UstmN=',i7,' DownN=',i7,' DestN=',i7,' STime=',f7.2,
     + 'Total Travel Time=',f7.2,'#of Nodes=',i4,'VehType',i2,'LOO',i2)
c	1890  format('Veh #',i7,' Tag=',i2,' info=',i2,' Ustm=',i,' Orig=',i7,
c	' Dest=',i7,' STime=',f7.2,' Total Travel Time=',f7.2,' # of Nodes=',i4, ' VehType',i2)
1891  format(10i7)
1892  format(10f7.2)

1893  format('Veh #',i7,'Tag=',i2,'Class=',i2,
     + 'UstmN=',i7,' DownN=',i7,' DestN=',i7,' STime=',f7.2,
     + 'Total Travel Time=',f7.2,'#of Nodes=',i4,'VehType',i2)

     	do ibus=1,nubus
       	if(busid(ibus).eq.j) then
         write(188,*) 'Statistics for bus number  ',ibus,distans(j)
         write(188,1893) j,itag(j),info(j),nodenum(iunod(isec(j))),
     +  nodenum(nint(VhcAtt_Value(j,1,1))),
     +  nodenum(nint(VhcAtt_Value(j,VhcAtt_Size(j)-1,1))),stime(j),
     +  tmp1,nnpath(j)-1,vehclass2(j)
         write(188,1891) (nodenum(nint(VhcAtt_Value(j,js,1))),js=1,
     +  VhcAtt_Size(j)-1)
         write(188,*)    '==>Node Exit Time Point'
         write(188,1892) (VhcAtt_Value(j,jn,3),jn=1,VhcAtt_Size(j)-1)
         write(188,*)    '==>Link Travel Time'
         write(188,1892) (VhcAtt_Value(j,jn,4),jn=1,VhcAtt_Size(j)-1)
         write(188,*)    '==>Accumulated Stop Time'
         write(188,1892) (VhcAtt_Value(j,jn,2),jn=1,VhcAtt_Size(j)-1)
         write(188,*)
     	 endif
     	enddo
   	endif
! --

!   if(HOVFlag(j).and.ioc(j).eq.1)then
!      iactual_lov_hot=iactual_lov_hot+1
!      time_lov_hot=time_lov_hot+ttilnow(j)
!   elseif (.not.HOVFlag(j).and.ioc(j).eq.1)then
!      iactual_lov_ohot=iactual_lov_ohot+1
!      time_lov_ohot=time_lov_ohot+ttilnow(j)
!   elseif(HOVFlag(j).and.ioc(j).eq.2)then
!      iactual_hov_hot=iactual_hov_hot+1
!      time_hov_hot=time_hov_hot+ttilnow(j)
!   elseif(.not.HOVFlag(j).and.ioc(j).eq.2)then
!      iactual_hov_ohot=iactual_hov_ohot+1
!      time_hov_ohot=time_hov_ohot+ttilnow(j)
!   endif

   	if(HOTFlag(j).and.ioc(j).eq.1)then ! lov on HOT
      iactual_lov_hot=iactual_lov_hot+1
      time_lov_hot=time_lov_hot+ttilnow(j)
   	elseif (.not.HOTFlag(j).and.ioc(j).eq.1)then ! lov on non-HOT
      iactual_lov_ohot=iactual_lov_ohot+1
      time_lov_ohot=time_lov_ohot+ttilnow(j)
   	elseif(HOTFlag(j).and.ioc(j).eq.2)then ! hov on HOT
      iactual_hov_hot=iactual_hov_hot+1
      time_hov_hot=time_hov_hot+ttilnow(j)
   	elseif(.not.HOTFlag(j).and.ioc(j).eq.2)then ! hov on non-HOT
      iactual_hov_ohot=iactual_hov_ohot+1
      time_hov_ohot=time_hov_ohot+ttilnow(j)
   	endif

   	if(ioc(j).eq.1)then ! lov 
      iactual_lov=iactual_lov+1
      time_lov=time_lov+ttilnow(j)
   	else ! hov
      iactual_hov=iactual_hov+1
      time_hov=time_hov+ttilnow(j)
   	endif


   	www = 0
   	if(itag(j).eq.2)then
     	if(NoOfIntDst(j).gt.1) then
	    do ka=1,NoOfIntDst(j)-1
          www = www + IntDestDwell(j,ka)
        enddo
     	endif
     	stoptemp = ttstop(j)
     	stoptime = stoptime + ttstop(j)
     	ttt=max(0.0,atime(j)-stime(j)-ttilnow(j)- www)
     	entry_queue1=entry_queue1+ttt
     	tt=atime(j)-stime(j)- www
     	triptime1=triptime1+tt
     	dtotal1=dtotal1+distans(j)
     	vtothr1=vtothr1+ttilnow(j)
     	itag2=itag2+1
     	if(info(j).eq.1) then
       entry_queue2=entry_queue2+ttt
       triptime2=triptime2+tt
       information=information+1
       vtothr2=vtothr2+ttilnow(j)
       dtotal2=dtotal2+distans(j)
       stopinfo=stopinfo+stoptemp
       switch(j)=iabs(switch(j))-1
       totaldecision=decision(j)+totaldecision
       totalswitch=switch(j)+totalswitch
       if(NoOfIntDst(j).eq.1) then
          entry_queue2_1=entry_queue2_1+ttt
          triptime2_1=triptime2_1+tt
          information_1=information_1+1
          vtothr2_1=vtothr2_1+ttilnow(j)
          dtotal2_1=dtotal2_1+distans(j)
          stopinfo_1=stopinfo_1+stoptemp
       elseif(NoOfIntDst(j).eq.2) then
          entry_queue2_2=entry_queue2_2+ttt
          triptime2_2=triptime2_2+tt
          information_2=information_2+1
          vtothr2_2=vtothr2_2+ttilnow(j)
          dtotal2_2=dtotal2_2+distans(j)
          stopinfo_2=stopinfo_2+stoptemp
       elseif(NoOfIntDst(j).eq.3) then
          entry_queue2_3=entry_queue2_3+ttt
          triptime2_3=triptime2_3+tt
          information_3=information_3+1
          vtothr2_3=vtothr2_3+ttilnow(j)
          dtotal2_3=dtotal2_3+distans(j)
          stopinfo_3=stopinfo_3+stoptemp
       endif
       do is=1,nu_switch+1
          if(switch(j).eq.is-1) switchnum(is)=switchnum(is)+1
       enddo
       do is=1,nu_switch+1
          if(decision(j).eq.is-1) decisionnum(is)=decisionnum(is)+1
       enddo
       if(switch(j).gt.nu_switch)  
     + switchnum(nu_switch+1)=switchnum(nu_switch+1)+1
       if(decision(j).gt.nu_switch) 
     + decisionnum(nu_switch+1)=decisionnum(nu_switch+1)+1
   
      elseif(info(j).eq.0) then
	   entry_queue3=entry_queue3+ttt
       triptime3=triptime3+tt
       noinformation=noinformation+1
       vtothr3=vtothr3+ttilnow(j)
       dtotal3=dtotal3+distans(j)
       stopnoinfo=stopnoinfo+stoptemp
       if(NoOfIntDst(j).eq.1) then
          entry_queue3_1=entry_queue3_1+ttt
          triptime3_1=triptime3_1+tt
          noinformation_1=noinformation_1+1
          vtothr3_1=vtothr3_1+ttilnow(j)
          dtotal3_1=dtotal3_1+distans(j)
          stopnoinfo_1=stopnoinfo_1+stoptemp
       elseif(NoOfIntDst(j).eq.2) then
          entry_queue3_2=entry_queue3_2+ttt
          triptime3_2=triptime3_2+tt
          noinformation_2=noinformation_2+1
          vtothr3_2=vtothr3_2+ttilnow(j)
          dtotal3_2=dtotal3_2+distans(j)
          stopnoinfo_2=stopnoinfo_2+stoptemp
       elseif(NoOfIntDst(j).eq.3) then
          entry_queue3_3=entry_queue3_3+ttt
          triptime3_3=triptime3_3+tt
          noinformation_3=noinformation_3+1
          vtothr3_3=vtothr3_3+ttilnow(j)
          dtotal3_3=dtotal3_3+distans(j)
          stopnoinfo_2=stopnoinfo_2+stoptemp
       endif
      endif
	elseif(itag(j).eq.0) then
       itag0=itag0+1
	endif
! --
! -- To avoid printing information for the bus after it exists the network
! --
    	do ibs=1,nubus
       if(busid(ibs).eq.j) busid(ibs)=nu_ve+1
    	enddo
! ---   Now we may re-use index j for a new vehicle

      return
      end
