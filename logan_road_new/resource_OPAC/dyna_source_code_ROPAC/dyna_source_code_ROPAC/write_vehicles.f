       subroutine write_vehicles
    
       use muc_mod
       use vector_mod
	open(file='output_vehicle.dat',unit=97,status='unknown')
	open(file='output_path.dat',unit=98,status='unknown')
	open(file='output_vehicle_in.dat',unit=977,status='unknown')
	open(file='output_path_in.dat',unit=988,status='unknown')

	icount=0											
c    	write(97,*) jj-nubus,noofstops

c	write(97,*) ktotal_out-nubus,noofstops
	write(97,*) jj,noofstops	
	write(977,*) jj-ktotal_out-nubus,noofstops

c	write(97,*) '     #   usec   dsec   stime vehcls vehtype ioc #ONode #IntDe info ribf   comp'
c 	change 'vehcls' to 'usrcls'
      do kj=1,jj
c    	if(kj.eq.4092) print *,'Alexnotin',notin(kj),vehclass2(kj)
c	print *, 'Alex551'	
      if(realdm.ne.1)then	
c      call links_travel_time(kj)
      endif
c	print *, 'Alex552'	
C      if(vehclass2(kj).ne.7.and.notin(kj).eq.1)then 								! notin =1, the vehicle is out of the network
       icount=icount+1

c	if(vehclass(kj).lt.1) vehclass(kj)=1

c     write(97,301) icount,nodenum(iunod(isec(kj))),nodenum(idnod(isec(kj))),stime(kj),vehclass(kj),vehclass2(kj),ioc(kj),VhcATT_Size(kj),NoOfIntDst(kj),info(kj),ribf(kj),compliance(kj)
        write(97,301) icount,nodenum(iunod(isec(kj))),nodenum(
     +  idnod(isec(kj))),stime(kj),vehclass(kj),vehclass2(kj),
     +  ioc(kj),VhcATT_Size(kj),NoOfIntDst(kj),info(kj),ribf(kj),
     +  compliance(kj),jorigin(kj)

 	  do j_ah=1,NoOfIntDst(kj) ! write out zone number in terms original zone number not master_zone
c     write(97,400) IntDestZone(kj,j_ah),IntDestDwell(kj,j_ah)
c     write(97,400) izone(nodenum(nint(VhcAtt_Value(kj,VhcATT_Size(kj)-1,1)))),IntDestDwell(kj,j_ah)
	    if(iConZone(nint(VhcAtt_Value(kj,VhcATT_Size(kj)-1,
     +      1)),2).gt.0)then
            write(97,400) iConZone(nint(VhcAtt_Value(kj,
     +      VhcATT_Size(kj)-1,1)),2),IntDestDwell(kj,j_ah)
c		 exit
          else
            write(97,400) izone(nint(VhcAtt_Value(kj,
     +      VhcATT_Size(kj)-1,1))),IntDestDwell(kj,j_ah)
c		 exit
	    endif
        enddo

        write(98,700) nodenum(iunod(isec(kj))),(nodenum(
     +  nint(VhcAtt_Value(kj,js,1))),js=1,VhcATT_Size(kj)-1)

C        else																		! Vehicles still in
       goto  2020
!	    print *, 'find class 7 veh'

        write(977,301) kj,nodenum(iunod(isec(kj))),nodenum(
     +  idnod(isec(kj))),stime(kj),vehclass(kj),vehclass2(kj),
     +  ioc(kj),VhcATT_Size(kj),NoOfIntDst(kj),info(kj),ribf(kj),
     +  compliance(kj),jorigin(kj)

      do j_ah=1,NoOfIntDst(kj) ! write out zone number in terms original zone number not master_zone
c     write(97,400) IntDestZone(kj,j_ah),IntDestDwell(kj,j_ah)
c     write(97,400) izone(nodenum(nint(VhcAtt_Value(kj,VhcATT_Size(kj)-1,1)))),IntDestDwell(kj,j_ah)
         if(iConZone(nint(VhcAtt_Value(kj,VhcATT_Size(kj)-1,
     +      1)),2).gt.0)then
            write(977,400) iConZone(nint(VhcAtt_Value(kj,
     +      VhcATT_Size(kj)-1,1)),2),IntDestDwell(kj,j_ah)
          else
            write(977,400) izone(nint(VhcAtt_Value(kj,
     +      VhcATT_Size(kj)-1,1))),IntDestDwell(kj,j_ah)
         endif
        enddo

        write(988,700)nodenum(iunod(isec(kj))),(nodenum(
     +  nint(VhcAtt_Value(kj,js,1))),js=1,VhcATT_Size(kj)-1)
	
C        endif

2020      enddo





      izero=0
      write(97,*) izero
      write(977,*) izero
301   format(3i7,f8.2,6i6,2f8.4,i5)
400   format(i12,f7.2)
700   format(280i7)
302	  format(1i6)
      close(977)
      close(988)
      return
      end
