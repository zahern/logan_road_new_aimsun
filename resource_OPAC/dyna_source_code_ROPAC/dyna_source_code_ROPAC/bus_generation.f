      subroutine bus_generation(icu,tt)
c  --
c -- This subroutine generates the buses and assignes all the attributes to it.
c --
c -- This subroutine is called from vehicle_loading, every simulation interval
c -- and it does not call any subroutines.
c --
c -- INPUT :
c --   ilink : current link
c --      tt : current clock time.
c --
c -- OUTPUT :
c --   bus attributes
c --
      use muc_mod
	use vector_mod
      use LinkList_mod

	integer Index1Dm ilink,icu
      real value
c --
c -- nubus : is the number of simulated buses
c --
c -- ngenbus(i) =0 if bus i is not generated yet, and 1 otherwise
c --  
      do 10 i=1,nubus
c --
c --  if ngenbus of the current bus =1, then skip it.
c --
       if(ngenbus(i).eq.1.or.icu.ne.buslink(i)) go to 10
c --
c -- If the starting time for the bus is at the current clock time
c -- and the generation link for the bus equals the current link,
c -- then generate the bus and assign all the attributes.
c --
         if(abs(busstart(i)-tt).lt.0.05) then
	      ilink = buslink(i)

             ngenbus(i)=1
	       TotalBusGen=TotalBusGen+1
c --
c -- vehicle's attributes
c --   
c --  Assign a vehicle ID for the bus
c --
            jj=jj+1
	      if(realdm.ne.1) then
              j1=jrestore+ 1
	      else
	        j1 = jj
	      endif
      	  jrestore = jrestore + 1
	      

            if(j1.gt.nu_ve) then
              jerror=0
              do k=1,nu_ve
                if(notin(k).eq.1) then
                  j1=k
                   notin(k)=0
                   jerror=1 
  	             exit
	          endif
              enddo
              if(jerror.eq.0) then
                write(911,*) 'ERROR'
                write(911,*) 'Number of vehicles in the network > nu_ve'
                write(911,*) 'To Resolve :'
                write(911,*) 'Increase nu_ve in the paramter file'
                stop
              endif
            endif
c --       
           numcars=numcars+1
           busid(i)=j1
           npar(ilink)=npar(ilink)+1
           if(vehclass2(j1).eq.2.or.vehclass2(j1).eq.5.or.
     *        vehclass2(j1).eq.7) nTruck(ilink)=nTruck(ilink)+1
	     volume(ilink)=volume(ilink)+1
           mtnum(j1)=2
           partotal(ilink)=partotal(ilink)+mtnum(j1)
	     if(maxden*xl(ilink)-partotal(ilink).lt.0) then
	       write(911,*) 'Error!! Possibly wrong setting in vehicle'
	       write(911,*) ' type in scenario.dat'
	       stop
	     endif

           call mtxj_insert(ilink,j1) !LST

           stime(j1)=tt
           ttilnow(j1)=0
           ttstop(j1)=0
           icurrnt(j1)=1
           distans(j1)=0.0
           xpar(j1)=s(ilink)/2
           if(tt.ge.starttm.and.tt.lt.endtm) then
		   itag(j1)=1
           else
	       itag(j1)=0
           endif
           isec(j1)=buslink(i)
!           nnpath(j1)=NoBusNode(i)

           nnpath(j1)=NoBusNode(i)+1
           vehclass2(j1)=7
	     vehclass(j1)=1
      	     do k=1,NoBusNode(i)+1
             value = BusAtt_Value(i,k,1)
		   call VhcAtt_Insert(j1,k,1,value)
	       enddo
            itmp = NoBusNode(i)
        !jdest(j1)=MasterDest(izone(BusAtt_Value(i,itmp,1)))
            

		  !jdest(j1)=iConZone(izone(BusAtt_Value(i,itmp+1,1)),2)
	      

		  jdest(j1)=izone(iConZone((BusAtt_Value(i,itmp,1)),2))
	
	          
		 
		 if(jdest(j1).eq.0)then
			 write(911,*) "Error in bus generation"
	        write(911,*) "Check the destination for bus:",i
	        Stop
             endif


c  -- under regular muc, assign one destination
        DestVisit(j1) = 1 
        NoOfIntDst(j1) = 1
        IntDestZone(j1,NoOfIntDst(j1))=jdest(j1)        


c -- endif for the condition on the starting time.
      endif

10    continue

      return
      end
     

